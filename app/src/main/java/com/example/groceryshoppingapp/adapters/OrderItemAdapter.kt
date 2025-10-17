package com.example.groceryshoppingapp.adapters

import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.ItemQuantity

class OrderItemAdapter(
    private val items: MutableList<ItemQuantity>,
    private val isEditable: Boolean
) : RecyclerView.Adapter<OrderItemAdapter.ItemViewHolder>() {

    inner class ItemViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvItemName: TextView = view.findViewById(R.id.tv_item_name)
        val tvItemQty: TextView = view.findViewById(R.id.tv_item_quantity)
        val tvItemPrice: TextView = view.findViewById(R.id.tv_item_price)
        val tvItemComment: TextView = view.findViewById(R.id.tv_item_comment)

        val etItemQty: EditText = view.findViewById(R.id.et_item_quantity)
        val etItemPrice: EditText = view.findViewById(R.id.et_item_price)
        val etComment: EditText = view.findViewById(R.id.et_item_comment)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_item, parent, false)
        return ItemViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemViewHolder, position: Int) {
        val item = items[position]
        holder.tvItemName.text = item.name

        // 🟩 READ-ONLY VIEW (Customer)
        if (!isEditable) {
            holder.etItemQty.visibility = View.GONE
            holder.etItemPrice.visibility = View.GONE
            holder.etComment.visibility = View.GONE

            holder.tvItemQty.visibility = View.VISIBLE
            holder.tvItemPrice.visibility = View.VISIBLE
            holder.tvItemComment.visibility = if (!item.comment.isNullOrBlank()) View.VISIBLE else View.GONE

            holder.tvItemQty.text = "Qty: ${item.quantity}"
            holder.tvItemPrice.text = "₹ %.2f".format(item.price)
            holder.tvItemComment.text = "Comment: ${item.comment}"
        }

        // 🟦 EDITABLE VIEW (Shopkeeper)
        else {
            holder.tvItemQty.visibility = View.GONE
            holder.tvItemPrice.visibility = View.GONE
            holder.tvItemComment.visibility = View.GONE

            holder.etItemQty.visibility = View.VISIBLE
            holder.etItemPrice.visibility = View.VISIBLE
            holder.etComment.visibility = View.VISIBLE

            holder.etItemQty.setText(item.quantity.toString())
            holder.etItemPrice.setText(item.price.toString())
            holder.etComment.setText(item.comment ?: "")

            holder.etItemQty.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    val newQty = s?.toString()?.toIntOrNull()
                    if (newQty != null && newQty >= 0) item.quantity = newQty
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })

            holder.etItemPrice.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    val newPrice = s?.toString()?.toDoubleOrNull()
                    if (newPrice != null && newPrice >= 0.0) item.price = newPrice
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })

            holder.etComment.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    item.comment = s?.toString()
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })
        }
    }

    override fun getItemCount(): Int = items.size

    fun getUpdatedItems(): List<ItemQuantity> = items
}
