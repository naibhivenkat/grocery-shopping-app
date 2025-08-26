package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.CartItem

class OrderSummaryAdapter(private val itemList: List<CartItem>) :
    RecyclerView.Adapter<OrderSummaryAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val itemName: TextView = view.findViewById(R.id.text_item_name)
        val itemPrice: TextView = view.findViewById(R.id.text_item_price)
        val itemQuantity: TextView = view.findViewById(R.id.text_item_quantity)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_summary, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = itemList[position]
        holder.itemName.text = item.item.name
        holder.itemQuantity.text = "Qty: ${item.quantity}"
        holder.itemPrice.text = "₹%.2f".format(item.item.price * item.quantity)
    }

    override fun getItemCount(): Int = itemList.size
}
