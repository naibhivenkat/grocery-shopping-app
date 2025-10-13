package com.example.groceryshoppingapp

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.models.Order
import com.example.groceryshoppingapp.utils.SessionManager

class OrdersAdapter(
    private val orders: List<Order>,
    private val shopMap: Map<String, String> = emptyMap(), // shopId -> shopName mapping
    private val onStatusClick: (Order) -> Unit,
    private val highlightCancelled: Boolean = true
) : RecyclerView.Adapter<OrdersAdapter.OrderViewHolder>() {

    inner class OrderViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val shopName: TextView = view.findViewById(R.id.text_shop_name)
        val orderId: TextView = view.findViewById(R.id.order_id)
        val totalItems: TextView = view.findViewById(R.id.text_total_items)
        val totalPrice: TextView = view.findViewById(R.id.text_total_price)
        val statusButton: Button = view.findViewById(R.id.status_button)
        val container: View = view.findViewById(R.id.order_container)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): OrderViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_status, parent, false)
        return OrderViewHolder(view)
    }

    override fun onBindViewHolder(holder: OrderViewHolder, position: Int) {
        val order = orders[position]

        // Get role from SessionManager
        val role = SessionManager.getRole(holder.shopName.context)

        // Get customer name
        val customerName = order.customer.fullName?.takeIf { it.isNotEmpty() } ?: order.customer.username

        // Get shop name from order or shopMap
        //val shopName = order.shopName ?: shopMap[order.shopId] ?: "Unknown Shop"
        val shopName = order.shopName ?: shopMap[order.shopId] ?: "Unknown Shop"

        // Role-based display
        holder.shopName.text = if (role.equals("shopowner", true)) {
            // Shop owner sees customer
            "🧑 Customer Name: $customerName"
        } else {
            // Customer sees shop
            "🏪 Shop Name: $shopName"
        }

        // Order ID with emoji
        holder.orderId.text = "🧾 Order No. : ${order.orderUuid}"

        // Total items and total price
        val totalItems = order.items.sumOf { it.quantity.toInt() }
        val totalPrice = order.total ?: order.items.sumOf { it.price * it.quantity }
        holder.totalItems.text = "📦 Total Items : $totalItems"
        holder.totalPrice.text = "💰 Total Amount : $totalPrice"

        // Status button
        holder.statusButton.text = order.status
        holder.statusButton.setBackgroundColor(getStatusColor(holder.statusButton.context, order.status))
        holder.statusButton.setTextColor(ContextCompat.getColor(holder.statusButton.context, android.R.color.white))

        // Highlight cancelled orders
        val bgColorRes = if (highlightCancelled && order.status.equals("cancelled", true))
            R.color.order_bg_cancelled else R.color.order_bg
        holder.container.setBackgroundColor(ContextCompat.getColor(holder.container.context, bgColorRes))


        holder.itemView.setOnClickListener {
            onStatusClick(order)
        }
        // Status button click listener
        holder.statusButton.setOnClickListener { onStatusClick(order) }
    }

    override fun getItemCount(): Int = orders.size

    private fun getStatusColor(context: Context, status: String): Int {
        return when (status.lowercase()) {
            "pending" -> ContextCompat.getColor(context, R.color.orange_500)
            "packed" -> ContextCompat.getColor(context, R.color.blue_500)
            "delivered" -> ContextCompat.getColor(context, R.color.green_500)
            "cancelled" -> ContextCompat.getColor(context, R.color.red_500)
            else -> ContextCompat.getColor(context, android.R.color.darker_gray)
        }
    }
}
