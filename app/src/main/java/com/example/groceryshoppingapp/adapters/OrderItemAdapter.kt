package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.ItemQuantity

class OrderItemAdapter(
    private val items: List<ItemQuantity>
) : RecyclerView.Adapter<OrderItemAdapter.ItemViewHolder>() {

    inner class ItemViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvItemName: TextView = view.findViewById(R.id.tv_item_name)
        val tvItemQty: TextView = view.findViewById(R.id.tv_item_quantity)
        val tvItemPrice: TextView = view.findViewById(R.id.tv_item_price)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_item, parent, false)
        return ItemViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemViewHolder, position: Int) {
        val itemQty = items[position]
        holder.tvItemName.text = itemQty.item.name
        holder.tvItemQty.text = "Qty: ${itemQty.quantity}"
        holder.tvItemPrice.text = "₹ %.2f".format(itemQty.item.price)
    }

    override fun getItemCount(): Int = items.size
}
